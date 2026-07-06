package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.SiteParamMultivarAnomalyRequest;
import com.example.waterbusiness.dto.SiteParamMultivarAnomalyResponse;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class SiteParamMultivarAnomalyService {

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;

    @Retry(name = "waterAiForecastRetry")
    public SiteParamMultivarAnomalyResponse detect(SiteParamMultivarAnomalyRequest request) {
        SiteParamMultivarAnomalyRequest pyBody = SiteParamMultivarAnomalyRequest.builder()
                .siteNo(request.getSiteNo() != null ? request.getSiteNo().trim() : "")
                .featuresCsvPath(blankToNull(request.getFeaturesCsvPath()))
                .referenceUtc(blankToNull(request.getReferenceUtc()))
                .build();
        return waterAiMaintenanceClient.anomalySiteParamMultivarFromFeatures(pyBody);
    }

    private static String blankToNull(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        return s;
    }
}
