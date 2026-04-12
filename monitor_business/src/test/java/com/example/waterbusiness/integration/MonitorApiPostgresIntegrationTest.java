package com.example.waterbusiness.integration;

import com.example.waterbusiness.client.WaterAIClient;
import com.example.waterbusiness.client.WaterForecastClient;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.ModelCallLogRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.WaterQualityRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("integrationtest")
@Testcontainers(disabledWithoutDocker = true)
class MonitorApiPostgresIntegrationTest {

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
    private WaterQualityRepository waterQualityRepository;

    @Autowired
    private MonitorStationRepository monitorStationRepository;

    @Autowired
    private AlertEventRepository alertEventRepository;

    @Autowired
    private ModelCallLogRepository modelCallLogRepository;

    @MockBean
    private WaterAIClient waterAIClient;

    /** 避免集成测 Feign 误连 Python :8000 */
    @MockBean
    private WaterForecastClient waterForecastClient;

    @BeforeEach
    void cleanDb() {
        modelCallLogRepository.deleteAll();
        alertEventRepository.deleteAll();
        waterQualityRepository.deleteAll();
        monitorStationRepository.deleteAll();
        MonitorStation s = new MonitorStation();
        s.setStationCode("integration_test_station");
        s.setStationName("Integration test");
        s.setLatitude(47.6);
        s.setLongitude(-122.3);
        s.setExternalId("12117000");
        monitorStationRepository.save(s);
    }

    @Test
    void postCheck_persistsRecordAndSuccessLog_withoutAlert_whenLevelGood() throws Exception {
        WaterQualityResponse ai = new WaterQualityResponse();
        ai.setPollutionLevel("Good");
        when(waterAIClient.predict(any(WaterQualityRequest.class))).thenReturn(ai);

        ResponseEntity<String> res = restTemplate.postForEntity("/api/check", buildValidCheckRequest(), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode root = objectMapper.readTree(res.getBody());
        assertThat(root.get("code").asText()).isEqualTo("0");
        assertThat(root.get("data").get("pollution_level").asText()).isEqualTo("Good");

        assertThat(waterQualityRepository.count()).isEqualTo(1);
        assertThat(waterQualityRepository.findAll().get(0).getStationId()).isNotNull();
        assertThat(modelCallLogRepository.findAll()).hasSize(1);
        assertThat(modelCallLogRepository.findAll().get(0).isSuccess()).isTrue();
        assertThat(alertEventRepository.count()).isZero();
    }

    @Test
    void postCheck_persistsAlert_whenLevelPoorAndMeetsThreshold() throws Exception {
        WaterQualityResponse ai = new WaterQualityResponse();
        ai.setPollutionLevel("Poor");
        when(waterAIClient.predict(any(WaterQualityRequest.class))).thenReturn(ai);

        ResponseEntity<String> res = restTemplate.postForEntity("/api/check", buildValidCheckRequest(), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode root = objectMapper.readTree(res.getBody());
        assertThat(root.get("data").get("pollution_level").asText()).isEqualTo("Poor");

        assertThat(waterQualityRepository.count()).isEqualTo(1);
        assertThat(alertEventRepository.count()).isEqualTo(1);
        assertThat(alertEventRepository.findAll().get(0).getStatus()).isEqualTo("NEW");
    }

    private WaterQualityRequest buildValidCheckRequest() {
        WaterQualityRequest request = new WaterQualityRequest();
        request.setWaterTemperatureC(24.5);
        request.setPH(7.1);
        request.setDissolvedOxygenMgL(6.9);
        request.setConductivityUSCm(305.0);
        request.setTurbidityNTU(4.0);
        request.setNitrateMgL(1.2);
        request.setAmmoniaNMgL(0.18);
        request.setTotalPhosphorusMgL(0.06);
        request.setCodMgL(16.5);
        request.setBodMgL(3.1);
        request.setHeavyMetalsPbUgL(4.2);
        request.setStationCode("integration_test_station");
        return request;
    }
}
