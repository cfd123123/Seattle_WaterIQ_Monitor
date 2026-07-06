package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.config.TurbidityRiskForecastProperties;
import com.example.waterbusiness.dto.TurbidityRiskForecast12hRequest;
import com.example.waterbusiness.dto.TurbidityRiskForecast12hResponse;
import feign.FeignException;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class TurbidityRiskForecastService {

    private static final Logger log = LoggerFactory.getLogger(TurbidityRiskForecastService.class);
    private static final String DEFAULT_SITE = "12117500";

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final TurbidityRiskForecastProperties properties;

    @Retry(name = "waterAiForecastRetry")
    public TurbidityRiskForecast12hResponse fetchForecast(String siteNo, String referenceUtc) {
        return waterAiMaintenanceClient.turbidityRiskForecast12h(buildRequest(siteNo, referenceUtc));
    }

    /**
     * 12h risk forecast plus LLM explanation. On assistant 502/503, falls back to forecast-only
     * and sets {@code explanation_error} so the UI can still show decision fields.
     */
    public TurbidityRiskForecast12hResponse fetchForecastWithExplain(String siteNo, String referenceUtc) {
        TurbidityRiskForecast12hRequest req = buildRequest(siteNo, referenceUtc);
        try {
            return waterAiMaintenanceClient.turbidityRiskExplain(req);
        } catch (FeignException e) {
            int status = e.status();
            if (status != 502 && status != 503) {
                throw e;
            }
            log.warn("turbidity risk-explain unavailable (HTTP {}), falling back to forecast-12h", status);
            TurbidityRiskForecast12hResponse forecast = waterAiMaintenanceClient.turbidityRiskForecast12h(req);
            forecast.setExplanationError(shortExplainFailureMessage(status));
            return forecast;
        }
    }

    private TurbidityRiskForecast12hRequest buildRequest(String siteNo, String referenceUtc) {
        String site = StringUtils.hasText(siteNo) ? siteNo.trim() : DEFAULT_SITE;
        return TurbidityRiskForecast12hRequest.builder()
                .siteNo(site)
                .featuresCsvPath(properties.getFeaturesCsvPath())
                .thresholdsJsonPath(properties.getThresholdsJsonPath())
                .referenceUtc(StringUtils.hasText(referenceUtc) ? referenceUtc.trim() : null)
                .build();
    }

    private static String shortExplainFailureMessage(int status) {
        if (status == 503) {
            return "AI summary unavailable (assistant disabled or not configured).";
        }
        return "AI summary unavailable (LLM request failed).";
    }
}
