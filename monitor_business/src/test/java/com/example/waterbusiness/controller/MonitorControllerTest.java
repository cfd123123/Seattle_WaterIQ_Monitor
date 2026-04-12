package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.WaterQualityBatchRequest;
import com.example.waterbusiness.dto.WaterQualityBatchResponse;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import com.example.waterbusiness.entity.WaterQualityRecord;
import com.example.waterbusiness.service.WaterQualityService;
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
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(MonitorController.class)
class MonitorControllerTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private WaterQualityService waterQualityService;

    @Test
    void check_shouldReturnOkWrappedResponse() throws Exception {
        WaterQualityResponse response = new WaterQualityResponse();
        response.setPollutionLevel("Poor");
        when(waterQualityService.checkAndSave(any())).thenReturn(response);

        mockMvc.perform(post("/api/check")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(buildValidRequest())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.pollution_level").value("Poor"));
    }

    @Test
    void check_shouldReturn400WhenRequestInvalid() throws Exception {
        WaterQualityRequest invalid = new WaterQualityRequest();
        invalid.setPH(7.1);

        mockMvc.perform(post("/api/check")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(invalid)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_ERROR"));
    }

    @Test
    void checkBatch_shouldReturnOk() throws Exception {
        WaterQualityBatchResponse response = WaterQualityBatchResponse.builder()
                .successCount(1)
                .failCount(0)
                .results(List.of())
                .build();
        when(waterQualityService.checkBatch(any())).thenReturn(response);

        WaterQualityBatchRequest request = new WaterQualityBatchRequest();
        request.setItems(List.of(buildValidRequest()));

        mockMvc.perform(post("/api/check/batch")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.successCount").value(1))
                .andExpect(jsonPath("$.data.failCount").value(0));
    }

    @Test
    void records_shouldReturnPageResponseShape() throws Exception {
        WaterQualityRecord record = new WaterQualityRecord();
        record.setPollutionLevel("Good");
        when(waterQualityService.listRecords(any()))
                .thenReturn(new PageImpl<>(List.of(record), PageRequest.of(0, 20), 1));

        mockMvc.perform(get("/api/records?page=0&size=20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.totalElements").value(1))
                .andExpect(jsonPath("$.data.content[0].pollutionLevel").value("Good"));
    }

    private static WaterQualityRequest buildValidRequest() {
        WaterQualityRequest request = new WaterQualityRequest();
        request.setWaterTemperatureC(24.5);
        request.setPH(7.1);
        request.setDissolvedOxygenMgL(6.9);
        request.setConductivityUSCm(305.0);
        request.setTurbidityNTU(4.0);
        request.setNitrateMgL(1.2);
        request.setAmmoniaNMgL(0.18);
        request.setTotalPhosphorusMgL(0.06);
        request.setCodMgL(16.5);
        request.setBodMgL(3.1);
        request.setHeavyMetalsPbUgL(4.2);
        request.setStationCode("puget_12117000");
        return request;
    }
}
