package com.example.waterbusiness.client;

import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "waterAIClient", url = "${water.ai.base-url:http://localhost:8000}")
public interface WaterAIClient {

    @PostMapping(value = "/predict", consumes = MediaType.APPLICATION_JSON_VALUE)
    WaterQualityResponse predict(@RequestBody WaterQualityRequest request);
}
