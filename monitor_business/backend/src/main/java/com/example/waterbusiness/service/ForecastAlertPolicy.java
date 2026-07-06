package com.example.waterbusiness.service;

import com.example.waterbusiness.domain.PollutionLevelThresholds;

/**
 * Maps forecast value to pollution level (MVP rules).
 * Only parameter_cd=63680 (turbidity) is bucketed; others return null (no forecast alert).
 */
public final class ForecastAlertPolicy {

    private ForecastAlertPolicy() {
    }

    public static String forecastLevel(String parameterCd, Double value) {
        if (parameterCd == null || value == null) {
            return null;
        }
        String p = parameterCd.trim();
        if ("63680".equals(p)) {
            double v = value;
            if (v <= 5.0) return "Excellent";
            if (v <= 20.0) return "Good";
            if (v <= 50.0) return "Moderate";
            if (v <= 100.0) return "Poor";
            return "Very Poor";
        }
        return null;
    }

    public static boolean shouldForecastAlert(String level, int threshold) {
        return PollutionLevelThresholds.shouldAlert(level, threshold);
    }
}
