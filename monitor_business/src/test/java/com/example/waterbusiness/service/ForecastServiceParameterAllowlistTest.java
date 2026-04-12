package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterForecastClient;
import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.dto.ForecastRequest;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assertions.assertEquals;

@ExtendWith(MockitoExtension.class)
class ForecastServiceParameterAllowlistTest {

    @Mock
    private WaterForecastClient waterForecastClient;
    @Mock
    private MonitorStationRepository monitorStationRepository;
    @Mock
    private AlertEventRepository alertEventRepository;
    @Mock
    private WaterAlertProperties waterAlertProperties;

    @InjectMocks
    private ForecastService forecastService;

    @Test
    void forecastWithRetry_rejectsWaterTemperatureParameter() {
        ForecastRequest req = new ForecastRequest();
        req.setSiteNo("12117000");
        req.setParameterCd("00010");
        req.setHorizonHours(12);

        assertThatThrownBy(() -> forecastService.forecastWithRetry(req))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(ex ->
                        assertEquals(400, ((ResponseStatusException) ex).getStatusCode().value()));
    }
}
