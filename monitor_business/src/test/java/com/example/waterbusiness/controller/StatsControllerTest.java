package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.StatsDistributionResponse;
import com.example.waterbusiness.dto.StatsOverviewResponse;
import com.example.waterbusiness.dto.StatsStationAlertTopItem;
import com.example.waterbusiness.dto.StatsStationAlertTopResponse;
import com.example.waterbusiness.dto.StatsTrendResponse;
import com.example.waterbusiness.service.StatsService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.when;
import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(StatsController.class)
class StatsControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private StatsService statsService;

    @Test
    void overview_shouldReturnOk() throws Exception {
        when(statsService.overview()).thenReturn(StatsOverviewResponse.builder()
                .totalCheckCount(10)
                .totalAlertCount(2)
                .build());

        mockMvc.perform(get("/api/stats/overview"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.totalCheckCount").value(10));
    }

    @Test
    void distribution_shouldReturnOk() throws Exception {
        when(statsService.distribution(any(), any()))
                .thenReturn(StatsDistributionResponse.builder()
                        .from(LocalDate.of(2026, 3, 1))
                        .to(LocalDate.of(2026, 3, 30))
                        .build());

        mockMvc.perform(get("/api/stats/distribution?from=2026-03-01&to=2026-03-30"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.from").value("2026-03-01"));
    }

    @Test
    void trend_shouldReturnBadRequestWhenServiceThrows() throws Exception {
        when(statsService.trend(any(), any(), any(), any()))
                .thenThrow(new ResponseStatusException(BAD_REQUEST, "查询跨度不能超过 365 天"));

        mockMvc.perform(get("/api/stats/trend?from=2024-01-01&to=2026-03-30&granularity=day"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("HTTP_400"));
    }

    @Test
    void trend_shouldReturnOk() throws Exception {
        when(statsService.trend(any(), any(), any(), any()))
                .thenReturn(StatsTrendResponse.builder()
                        .from(LocalDate.of(2026, 3, 1))
                        .to(LocalDate.of(2026, 3, 30))
                        .granularity("day")
                        .series(List.of())
                        .build());

        mockMvc.perform(get("/api/stats/trend?from=2026-03-01&to=2026-03-30&granularity=day"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.granularity").value("day"));
    }

    @Test
    void stationAlertTop_shouldReturnOk() throws Exception {
        when(statsService.stationAlertTop(anyInt(), anyInt()))
                .thenReturn(StatsStationAlertTopResponse.builder()
                        .days(7)
                        .topN(5)
                        .items(List.of(
                                StatsStationAlertTopItem.builder()
                                        .stationId(1L)
                                        .stationCode("puget_1")
                                        .stationName("Station A")
                                        .alertCount(3)
                                        .openAlertCount(2)
                                        .build()
                        ))
                        .build());

        mockMvc.perform(get("/api/stats/station-alert-top?days=7&topN=5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.items[0].station_code").value("puget_1"))
                .andExpect(jsonPath("$.data.items[0].alert_count").value(3));
    }
}
