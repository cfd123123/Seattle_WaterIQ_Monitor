package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAIClient;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class AiPredictService {

    private final WaterAIClient waterAIClient;

    @Retry(name = "waterAiPredictRetry")
    public WaterQualityResponse predictWithRetry(WaterQualityRequest request) {
        return waterAIClient.predict(request);
    }
}
