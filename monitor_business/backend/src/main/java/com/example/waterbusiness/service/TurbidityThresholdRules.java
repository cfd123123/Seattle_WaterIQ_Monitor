package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.TurbidityThresholdPointDto;

import java.util.List;

/**
 * Two-point IV turbidity rule: warn tier [warn, critical); critical when last point ≥ critical and previous ≥ warn (critical wins; no warn-then-upgrade path).
 */
public final class TurbidityThresholdRules {

    public enum Tier {
        NONE,
        WARN,
        CRITICAL
    }

    private TurbidityThresholdRules() {
    }

    /**
     * @param points time-ascending, at most 2 points (sorted in Python)
     */
    public static Tier classify(List<TurbidityThresholdPointDto> points, double warnNtu, double criticalNtu) {
        if (points == null || points.size() < 2) {
            return Tier.NONE;
        }
        TurbidityThresholdPointDto p1 = points.get(0);
        TurbidityThresholdPointDto p2 = points.get(1);
        if (p1.getNtu() == null || p2.getNtu() == null) {
            return Tier.NONE;
        }
        double v1 = p1.getNtu();
        double v2 = p2.getNtu();
        if (v2 >= criticalNtu && v1 >= warnNtu) {
            return Tier.CRITICAL;
        }
        if (v1 >= warnNtu && v2 >= warnNtu && v2 < criticalNtu) {
            return Tier.WARN;
        }
        return Tier.NONE;
    }
}
