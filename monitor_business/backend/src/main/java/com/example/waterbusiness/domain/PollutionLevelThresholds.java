package com.example.waterbusiness.domain;

import java.util.Locale;
import java.util.Map;

/**
 * Hard-coded order aligned with training CSV Pollution_Level; higher score = worse pollution.
 * Alerting uses {@code water.alert.threshold} vs {@link #scoreOf(String)}.
 */
public final class PollutionLevelThresholds {

    private static final Map<String, Integer> ORDER = Map.ofEntries(
            Map.entry("excellent", 1),
            Map.entry("good", 2),
            Map.entry("moderate", 3),
            Map.entry("poor", 4),
            Map.entry("very poor", 5)
    );

    private PollutionLevelThresholds() {
    }

    /**
     * @return 1–5; unknown labels return 0 (no numeric alert)
     */
    public static int scoreOf(String pollutionLevel) {
        if (pollutionLevel == null || pollutionLevel.isBlank()) {
            return 0;
        }
        String key = pollutionLevel.trim().toLowerCase(Locale.ROOT);
        return ORDER.getOrDefault(key, 0);
    }

    public static boolean shouldAlert(String pollutionLevel, int threshold) {
        int s = scoreOf(pollutionLevel);
        return s > 0 && s >= threshold;
    }

    /**
     * Alert severity from score (fixed mapping for threshold rules).
     */
    public static String severityForScore(int score) {
        if (score >= 5) {
            return "HIGH";
        }
        if (score >= 4) {
            return "MEDIUM";
        }
        return "LOW";
    }
}
