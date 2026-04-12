package com.example.waterbusiness.controller;

import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.service.AlertService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(AlertController.class)
class AlertControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AlertService alertService;

    @Test
    void list_shouldReturnPagedAlerts() throws Exception {
        AlertEvent event = new AlertEvent();
        event.setId(1L);
        event.setStatus("NEW");
        event.setSeverity("MEDIUM");
        when(alertService.list(any(), any(), any(), any(), any(), any()))
                .thenReturn(new PageImpl<>(List.of(event), PageRequest.of(0, 20), 1));

        mockMvc.perform(get("/api/alerts?page=0&size=20&status=NEW"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.totalElements").value(1))
                .andExpect(jsonPath("$.data.content[0].status").value("NEW"));
    }

    @Test
    void ack_shouldReturnOk() throws Exception {
        doNothing().when(alertService).acknowledge(any(), any());

        mockMvc.perform(post("/api/alerts/1/ack")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                java.util.Map.of("acknowledgedBy", "operator", "remark", "ok")
                        )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"));
    }

    @Test
    void close_shouldReturnOk() throws Exception {
        doNothing().when(alertService).close(any(), any());

        mockMvc.perform(post("/api/alerts/1/close")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                java.util.Map.of("closedBy", "operator", "remark", "done")
                        )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"));
    }
}
