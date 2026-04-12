package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.AutoForecastBatchExecutionResult;
import com.example.waterbusiness.dto.AutoForecastBatchItemResult;
import com.example.waterbusiness.dto.AutoForecastSettingsResponse;
import com.example.waterbusiness.dto.AutoForecastSettingsUpdateRequest;
import com.example.waterbusiness.service.AutoForecastBatchService;
import com.example.waterbusiness.service.AutoForecastSettingsService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(AutoForecastSettingsController.class)
class AutoForecastSettingsControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AutoForecastSettingsService autoForecastSettingsService;

    @MockBean
    private AutoForecastBatchService autoForecastBatchService;

    @Test
    void getAutoSettings_shouldReturnOk() throws Exception {
        when(autoForecastSettingsService.getResponse()).thenReturn(
                AutoForecastSettingsResponse.builder()
                        .enabled(false)
                        .scheduleCron("0 0 2 * * ?")
                        .build()
        );

        mockMvc.perform(get("/api/forecast/auto-settings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.enabled").value(false));
    }

    @Test
    void putAutoSettings_shouldReturnOk() throws Exception {
        when(autoForecastSettingsService.setEnabled(true)).thenReturn(
                AutoForecastSettingsResponse.builder()
                        .enabled(true)
                        .scheduleCron("0 0 2 * * ?")
                        .build()
        );

        AutoForecastSettingsUpdateRequest body = new AutoForecastSettingsUpdateRequest();
        body.setEnabled(true);

        mockMvc.perform(put("/api/forecast/auto-settings")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.enabled").value(true));
    }

    @Test
    void postRunNow_shouldExecuteBatchAndReturnSettings() throws Exception {
        when(autoForecastBatchService.executeBatch()).thenReturn(
                new AutoForecastBatchExecutionResult(
                        "ok=1 fail=0",
                        List.of(
                                AutoForecastBatchItemResult.builder()
                                        .siteNo("12117000")
                                        .stationName("Test Station")
                                        .parameterCd("00060")
                                        .success(true)
                                        .forecastAvailable(true)
                                        .forecastValue(3.5)
                                        .build()
                        )
                )
        );
        when(autoForecastSettingsService.getResponse()).thenReturn(
                AutoForecastSettingsResponse.builder()
                        .enabled(false)
                        .scheduleCron("0 0 2 * * ?")
                        .lastRunSummary("ok=1 fail=0")
                        .build()
        );

        mockMvc.perform(post("/api/forecast/auto-settings/run-now"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.settings.last_run_summary").value("ok=1 fail=0"))
                .andExpect(jsonPath("$.data.batch_results[0].site_no").value("12117000"))
                .andExpect(jsonPath("$.data.batch_results[0].forecast_value").value(3.5));

        verify(autoForecastBatchService).executeBatch();
    }
}
