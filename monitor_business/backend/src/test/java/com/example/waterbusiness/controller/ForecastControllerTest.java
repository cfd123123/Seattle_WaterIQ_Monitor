package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ForecastRequest;
import com.example.waterbusiness.dto.ForecastResponse;
import com.example.waterbusiness.service.ForecastService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(ForecastController.class)
class ForecastControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ForecastService forecastService;

    @Test
    void forecast_shouldReturnOkWrappedResponse() throws Exception {
        ForecastResponse data = new ForecastResponse();
        data.setSiteNo("12117000");
        data.setParameterCd("00060");
        data.setHorizonHours(12);
        data.setForecastAvailable(true);
        data.setForecastValue(140.5);
        data.setModelVersion("forecast-ridge-recursive-v1");
        data.setDataPointsUsed(64);
        when(forecastService.forecastWithRetry(any())).thenReturn(data);

        ForecastRequest req = new ForecastRequest();
        req.setSiteNo("12117000");
        req.setParameterCd("00060");
        req.setHorizonHours(12);

        mockMvc.perform(post("/api/forecast")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.forecast_available").value(true))
                .andExpect(jsonPath("$.data.forecast_value").value(140.5));
    }

    @Test
    void forecast_shouldReturn400WhenParameterCdInvalid() throws Exception {
        ForecastRequest req = new ForecastRequest();
        req.setSiteNo("12117000");
        req.setParameterCd("60");
        req.setHorizonHours(12);

        mockMvc.perform(post("/api/forecast")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_ERROR"));
    }
}
