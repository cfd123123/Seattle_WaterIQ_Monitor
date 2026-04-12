package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.UsgsAnomalyFromIvRequest;
import com.example.waterbusiness.dto.UsgsAnomalyRequest;
import com.example.waterbusiness.dto.UsgsAnomalyResponse;
import com.example.waterbusiness.service.UsgsAnomalyService;
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

@WebMvcTest(UsgsAnomalyController.class)
class UsgsAnomalyControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private UsgsAnomalyService usgsAnomalyService;

    @Test
    void check_shouldReturnOk() throws Exception {
        UsgsAnomalyResponse r = new UsgsAnomalyResponse();
        r.setSiteNo("12117000");
        r.setModelVersion("usgs-iforest-v1");
        r.setAnomalyScore(0.56);
        r.setThreshold(0.43);
        r.setIsAnomaly(true);
        r.setAlertCreated(true);
        r.setAlertReason("alert_created");
        when(usgsAnomalyService.detectAndAlert(any())).thenReturn(r);

        UsgsAnomalyRequest req = new UsgsAnomalyRequest();
        req.setSiteNo("12117000");
        req.setV00010(14.2);
        req.setV00400(7.1);
        req.setV00300(8.8);
        req.setV00095(210.0);
        req.setV63680(12.0);

        mockMvc.perform(post("/api/usgs/anomaly/check")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.is_anomaly").value(true))
                .andExpect(jsonPath("$.data.alert_created").value(true));
    }

    @Test
    void checkFromIv_shouldReturnOk() throws Exception {
        UsgsAnomalyResponse r = new UsgsAnomalyResponse();
        r.setSiteNo("12117000");
        r.setModelVersion("usgs-iforest-v1");
        r.setAnomalyScore(0.51);
        r.setThreshold(0.43);
        r.setIsAnomaly(false);
        r.setAlertCreated(false);
        r.setAlertReason("not_anomaly");
        r.setSampleDatetime("2026-01-01T12:00:00+00:00");
        when(usgsAnomalyService.detectAndAlertFromIv(any())).thenReturn(r);

        UsgsAnomalyFromIvRequest req = new UsgsAnomalyFromIvRequest();
        req.setSiteNo("12117000");

        mockMvc.perform(post("/api/usgs/anomaly/check-from-iv")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.is_anomaly").value(false))
                .andExpect(jsonPath("$.data.sample_datetime").value("2026-01-01T12:00:00+00:00"));
    }
}
