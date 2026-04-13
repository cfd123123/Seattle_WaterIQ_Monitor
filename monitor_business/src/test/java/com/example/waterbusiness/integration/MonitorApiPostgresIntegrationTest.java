package com.example.waterbusiness.integration;

import com.example.waterbusiness.client.WaterForecastClient;
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
    private MonitorStationRepository monitorStationRepository;

    @Autowired
    private AlertEventRepository alertEventRepository;

    /** 避免集成测 Feign 误连 Python :8000 */
    @MockBean
    private WaterForecastClient waterForecastClient;

    @BeforeEach
    void cleanDb() {
        alertEventRepository.deleteAll();
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
    void getMapStations_returnsRegisteredStation() throws Exception {
        ResponseEntity<String> res = restTemplate.getForEntity("/api/map/stations", String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode root = objectMapper.readTree(res.getBody());
        assertThat(root.get("code").asText()).isEqualTo("0");
        assertThat(root.get("data").isArray()).isTrue();
        assertThat(root.get("data")).hasSize(1);
        assertThat(root.get("data").get(0).get("stationCode").asText()).isEqualTo("integration_test_station");
    }
}
