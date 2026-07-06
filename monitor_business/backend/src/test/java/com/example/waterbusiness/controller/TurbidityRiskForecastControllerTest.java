package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.TurbidityRiskForecast12hResponse;
import com.example.waterbusiness.service.TurbidityRiskForecastService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(TurbidityRiskForecastController.class)
class TurbidityRiskForecastControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private TurbidityRiskForecastService turbidityRiskForecastService;

    @Test
    void forecast12h_shouldReturnOk() throws Exception {
        TurbidityRiskForecast12hResponse body = new TurbidityRiskForecast12hResponse();
        body.setSiteNo("12117500");
        body.setAlert12hForecast(1);
        body.setMaxTierForecast("WATCH");
        body.setRecommendAlert(true);
        body.setRationaleTemplateKey("forecast.turbidityRisk.rationale.persistenceElevated");
        when(turbidityRiskForecastService.fetchForecast("12117500", null)).thenReturn(body);

        mockMvc.perform(post("/api/usgs/turbidity-risk/forecast-12h").param("siteNo", "12117500"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.recommend_alert").value(true))
                .andExpect(jsonPath("$.data.max_tier_forecast").value("WATCH"));
    }

    @Test
    void riskExplain_shouldReturnOk() throws Exception {
        TurbidityRiskForecast12hResponse body = new TurbidityRiskForecast12hResponse();
        body.setSiteNo("12117500");
        body.setAlert12hForecast(0);
        body.setMaxTierForecast("NORMAL");
        body.setRecommendAlert(false);
        body.setExplanationText("Site 12117500 is currently at NORMAL tier.");
        when(turbidityRiskForecastService.fetchForecastWithExplain("12117500", null)).thenReturn(body);

        mockMvc.perform(post("/api/usgs/turbidity-risk/risk-explain").param("siteNo", "12117500"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.explanation_text").value("Site 12117500 is currently at NORMAL tier."));
    }
}
