package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.TurbidityThresholdScanResult;
import com.example.waterbusiness.service.TurbidityThresholdAlertService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(TurbidityThresholdController.class)
class TurbidityThresholdControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private TurbidityThresholdAlertService turbidityThresholdAlertService;

    @Test
    void scanNow_shouldReturnOk() throws Exception {
        when(turbidityThresholdAlertService.scanAndAlert()).thenReturn(
                TurbidityThresholdScanResult.builder()
                        .stationsConsidered(2)
                        .alertsCreated(0)
                        .skippedNoData(0)
                        .skippedNoTrigger(2)
                        .skippedDuplicate(0)
                        .skippedRegisteredNo63680InIv(0)
                        .summary("considered=2 created=0")
                        .build()
        );

        mockMvc.perform(post("/api/usgs/turbidity-threshold/scan"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.stationsConsidered").value(2))
                .andExpect(jsonPath("$.data.alertsCreated").value(0));
    }
}
