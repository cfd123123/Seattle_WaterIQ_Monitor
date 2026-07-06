package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.MapStationPointResponse;
import com.example.waterbusiness.service.MapStationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(MonitorController.class)
class MonitorControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private MapStationService mapStationService;

    @Test
    void mapStations_shouldReturnOkWrappedList() throws Exception {
        when(mapStationService.listMapStations()).thenReturn(
                List.of(
                        MapStationPointResponse.builder()
                                .stationId(1L)
                                .stationCode("s1")
                                .stationName("S1")
                                .latitude(47.0)
                                .longitude(-122.0)
                                .openAlertCount(0L)
                                .build()
                )
        );

        mockMvc.perform(get("/api/map/stations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data[0].stationCode").value("s1"));
    }
}
