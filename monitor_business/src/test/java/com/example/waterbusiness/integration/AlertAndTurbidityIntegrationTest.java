package com.example.waterbusiness.integration;

import com.example.waterbusiness.client.WaterAIClient;
import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.client.WaterForecastClient;
import com.example.waterbusiness.dto.SitesWith63680Request;
import com.example.waterbusiness.dto.SitesWith63680Response;
import com.example.waterbusiness.dto.TurbidityThresholdBatchRequest;
import com.example.waterbusiness.dto.TurbidityThresholdBatchResponse;
import com.example.waterbusiness.dto.TurbidityThresholdPointDto;
import com.example.waterbusiness.dto.TurbidityThresholdSiteSnapshotDto;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 告警与浊度阈值：集成测（Testcontainers PostgreSQL + Mock Feign → Python）。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("integrationtest")
@Testcontainers(disabledWithoutDocker = true)
class AlertAndTurbidityIntegrationTest {

    private static final String USGS_SITE = "12117000";

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(DockerImageName.parse("postgres:16-alpine"));

    @DynamicPropertySource
    static void registerDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Autowired
    private TestRestTemplate restTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private AlertEventRepository alertEventRepository;

    @Autowired
    private MonitorStationRepository monitorStationRepository;

    @MockBean
    private WaterAIClient waterAIClient;

    @MockBean
    private WaterAiMaintenanceClient waterAiMaintenanceClient;

    /** 避免集成测上下文初始化时 Feign 误连 :8000 */
    @MockBean
    private WaterForecastClient waterForecastClient;

    @BeforeEach
    void cleanAndSeedStation() {
        alertEventRepository.deleteAll();
        monitorStationRepository.deleteAll();
        MonitorStation s = new MonitorStation();
        s.setStationCode("integration_turbidity_station");
        s.setStationName("Turbidity integration");
        s.setLatitude(47.6);
        s.setLongitude(-122.3);
        s.setExternalId(USGS_SITE);
        monitorStationRepository.save(s);
    }

    @Test
    void turbidityScan_createsWarnAlert_whenStubReturnsTwoPointsAboveThreshold() throws Exception {
        SitesWith63680Response sitesResp = new SitesWith63680Response();
        sitesResp.setSiteNos(List.of(USGS_SITE));
        when(waterAiMaintenanceClient.sitesWith63680(any(SitesWith63680Request.class))).thenReturn(sitesResp);

        TurbidityThresholdPointDto p1 = new TurbidityThresholdPointDto();
        p1.setDatetime("2026-01-01T00:00:00Z");
        p1.setNtu(55.0);
        TurbidityThresholdPointDto p2 = new TurbidityThresholdPointDto();
        p2.setDatetime("2026-01-01T00:15:00Z");
        p2.setNtu(60.0);
        TurbidityThresholdSiteSnapshotDto snap = new TurbidityThresholdSiteSnapshotDto();
        snap.setAvailable(true);
        snap.setPoints(List.of(p1, p2));
        Map<String, TurbidityThresholdSiteSnapshotDto> sitesMap = new HashMap<>();
        sitesMap.put(USGS_SITE, snap);
        TurbidityThresholdBatchResponse batchResp = new TurbidityThresholdBatchResponse();
        batchResp.setSites(sitesMap);
        when(waterAiMaintenanceClient.turbidityThresholdBatch(any(TurbidityThresholdBatchRequest.class)))
                .thenReturn(batchResp);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        ResponseEntity<String> res = restTemplate.postForEntity(
                "/api/usgs/turbidity-threshold/scan",
                new HttpEntity<>("{}", headers),
                String.class
        );

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode root = objectMapper.readTree(res.getBody());
        assertThat(root.get("code").asText()).isEqualTo("0");
        assertThat(root.get("data").get("alertsCreated").asInt()).isEqualTo(1);

        assertThat(alertEventRepository.count()).isEqualTo(1);
        AlertEvent saved = alertEventRepository.findAll().get(0);
        assertThat(saved.getRuleCode()).isEqualTo("USGS_TURBIDITY_THRESHOLD_V1_WARN");
        assertThat(saved.getAlertType()).isEqualTo("THRESHOLD_ALERT");
        assertThat(saved.getStationId()).isNotNull();
    }

    @Test
    void getAlerts_returnsPagedJson_withTwoInsertedAlerts() throws Exception {
        MonitorStation st = monitorStationRepository.findAll().get(0);
        LocalDateTime t = LocalDateTime.of(2026, 3, 1, 12, 0);
        AlertEvent e1 = new AlertEvent();
        e1.setWaterQualityRecordId(null);
        e1.setStationId(st.getId());
        e1.setAlertType("POLLUTION_THRESHOLD");
        e1.setSeverity("MEDIUM");
        e1.setStatus("NEW");
        e1.setPollutionLevel("Poor");
        e1.setTitle("水质等级告警: Poor");
        e1.setDetail("pollution_level=Poor, score=4");
        e1.setRuleCode("HARDCODED_LEVEL_THRESHOLD");
        e1.setCreatedAt(t);
        alertEventRepository.save(e1);

        AlertEvent e2 = new AlertEvent();
        e2.setWaterQualityRecordId(null);
        e2.setStationId(st.getId());
        e2.setAlertType("THRESHOLD_ALERT");
        e2.setSeverity("HIGH");
        e2.setStatus("NEW");
        e2.setPollutionLevel("Very Poor");
        e2.setTitle("USGS 浊度阈值告警（严重）");
        e2.setDetail("site_no=12117000, parameter_cd=63680");
        e2.setRuleCode("USGS_TURBIDITY_THRESHOLD_V1_CRITICAL");
        e2.setCreatedAt(t.plusHours(1));
        alertEventRepository.save(e2);

        ResponseEntity<String> res = restTemplate.getForEntity(
                "/api/alerts?page=0&size=20",
                String.class
        );

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode root = objectMapper.readTree(res.getBody());
        assertThat(root.get("code").asText()).isEqualTo("0");
        JsonNode data = root.get("data");
        assertThat(data.get("totalElements").asLong()).isEqualTo(2);
        assertThat(data.get("content").isArray()).isTrue();
        assertThat(data.get("content")).hasSize(2);
        // 默认按 createdAt DESC，最新一条在前
        JsonNode first = data.get("content").get(0);
        assertThat(first.get("ruleCode").asText()).isEqualTo("USGS_TURBIDITY_THRESHOLD_V1_CRITICAL");
        JsonNode second = data.get("content").get(1);
        assertThat(second.get("ruleCode").asText()).isEqualTo("HARDCODED_LEVEL_THRESHOLD");
    }
}
