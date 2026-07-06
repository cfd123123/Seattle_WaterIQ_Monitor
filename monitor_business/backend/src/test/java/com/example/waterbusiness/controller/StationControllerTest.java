package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.StationResponse;
import com.example.waterbusiness.dto.StationUpsertRequest;
import com.example.waterbusiness.service.MonitorStationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(StationController.class)
class StationControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private MonitorStationService monitorStationService;

    @Test
    void create_shouldReturnOk() throws Exception {
        StationResponse response = StationResponse.builder()
                .id(1L)
                .stationCode("puget_12117000")
                .stationName("Puget sample")
                .latitude(47.6021)
                .longitude(-122.3350)
                .status("ACTIVE")
                .build();
        when(monitorStationService.create(any())).thenReturn(response);

        StationUpsertRequest request = new StationUpsertRequest();
        request.setStationCode("puget_12117000");
        request.setLatitude(47.6021);
        request.setLongitude(-122.3350);

        mockMvc.perform(post("/api/stations")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.stationCode").value("puget_12117000"));
    }

    @Test
    void update_shouldReturnOk() throws Exception {
        StationResponse response = StationResponse.builder()
                .id(1L)
                .stationCode("puget_12117000")
                .stationName("Renamed")
                .latitude(47.6021)
                .longitude(-122.3350)
                .build();
        when(monitorStationService.update(eq("puget_12117000"), any())).thenReturn(response);

        StationUpsertRequest request = new StationUpsertRequest();
        request.setStationCode("puget_12117000");
        request.setStationName("Renamed");
        request.setLatitude(47.6021);
        request.setLongitude(-122.3350);

        mockMvc.perform(put("/api/stations/puget_12117000")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.stationName").value("Renamed"));
    }

    @Test
    void delete_shouldReturnOk() throws Exception {
        doNothing().when(monitorStationService).deleteByStationCode("puget_12117000");

        mockMvc.perform(delete("/api/stations/puget_12117000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"));
    }

    @Test
    void list_shouldReturnOk() throws Exception {
        when(monitorStationService.list()).thenReturn(List.of(
                StationResponse.builder()
                        .id(1L)
                        .stationCode("puget_12117000")
                        .latitude(47.6021)
                        .longitude(-122.3350)
                        .build()
        ));

        mockMvc.perform(get("/api/stations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data[0].stationCode").value("puget_12117000"));
    }
}
