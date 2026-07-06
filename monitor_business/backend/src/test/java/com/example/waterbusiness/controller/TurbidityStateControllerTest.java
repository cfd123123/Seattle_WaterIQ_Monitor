package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.TurbidityStateScanResult;
import com.example.waterbusiness.dto.TurbidityStateSnapshotResponse;
import com.example.waterbusiness.service.TurbidityStateAlertService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(TurbidityStateController.class)
class TurbidityStateControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private TurbidityStateAlertService turbidityStateAlertService;

    @Test
    void snapshot_shouldReturnOk() throws Exception {
        TurbidityStateSnapshotResponse snap = new TurbidityStateSnapshotResponse();
        snap.setSiteNo("12117500");
        snap.setState("Normal");
        snap.setTurbidityNtu(0.6);
        when(turbidityStateAlertService.fetchSnapshot("12117500", null)).thenReturn(snap);

        mockMvc.perform(get("/api/usgs/turbidity-state/snapshot").param("siteNo", "12117500"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.state").value("Normal"))
                .andExpect(jsonPath("$.data.turbidityNtu").value(0.6));
    }

    @Test
    void scanNow_shouldReturnOk() throws Exception {
        when(turbidityStateAlertService.scanAndAlert()).thenReturn(
                TurbidityStateScanResult.builder()
                        .stationsConsidered(1)
                        .alertsCreated(0)
                        .skippedNoTrigger(1)
                        .summary("considered=1")
                        .build()
        );

        mockMvc.perform(post("/api/usgs/turbidity-state/scan"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.stationsConsidered").value(1));
    }
}
