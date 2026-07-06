package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.service.SiteParamAnomalyService;
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

@WebMvcTest(SiteParamAnomalyController.class)
class SiteParamAnomalyControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private SiteParamAnomalyService siteParamAnomalyService;

    @Test
    void check_shouldReturnOk() throws Exception {
        SiteParamAnomalyIvResponse r = new SiteParamAnomalyIvResponse();
        r.setSiteNo("12117000");
        r.setParameterCd("00060");
        r.setAnomalyAvailable(true);
        r.setIsAnomaly(false);
        r.setAlertCreated(false);
        r.setAlertReason("not_anomaly");
        when(siteParamAnomalyService.detectAndAlert(any())).thenReturn(r);

        SiteParamAnomalyIvRequest req = SiteParamAnomalyIvRequest.builder()
                .siteNo("12117000")
                .parameterCd("00060")
                .build();

        mockMvc.perform(post("/api/usgs/anomaly/site-param/check")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.anomaly_available").value(true));
    }

    @Test
    void check_shouldReturn400WhenParameterInvalid() throws Exception {
        SiteParamAnomalyIvRequest req = SiteParamAnomalyIvRequest.builder()
                .siteNo("12117000")
                .parameterCd("00400")
                .build();

        mockMvc.perform(post("/api/usgs/anomaly/site-param/check")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isBadRequest());
    }
}
