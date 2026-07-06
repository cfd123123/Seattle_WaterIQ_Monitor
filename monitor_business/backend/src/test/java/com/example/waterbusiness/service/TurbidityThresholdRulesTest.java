package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.TurbidityThresholdPointDto;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class TurbidityThresholdRulesTest {

    private static TurbidityThresholdPointDto p(String t, double n) {
        TurbidityThresholdPointDto d = new TurbidityThresholdPointDto();
        d.setDatetime(t);
        d.setNtu(n);
        return d;
    }

    @Test
    void twoPointsInWarnBand() {
        assertEquals(
                TurbidityThresholdRules.Tier.WARN,
                TurbidityThresholdRules.classify(List.of(p("a", 55), p("b", 60)), 50, 100)
        );
    }

    @Test
    void criticalWhenLastAbove100AndPrevElevated() {
        assertEquals(
                TurbidityThresholdRules.Tier.CRITICAL,
                TurbidityThresholdRules.classify(List.of(p("a", 55), p("b", 110)), 50, 100)
        );
    }

    @Test
    void bothAbove100() {
        assertEquals(
                TurbidityThresholdRules.Tier.CRITICAL,
                TurbidityThresholdRules.classify(List.of(p("a", 120), p("b", 105)), 50, 100)
        );
    }

    @Test
    void recoveryNoAlert() {
        assertEquals(
                TurbidityThresholdRules.Tier.NONE,
                TurbidityThresholdRules.classify(List.of(p("a", 110), p("b", 40)), 50, 100)
        );
    }

    @Test
    void singleSpikeNoAlert() {
        assertEquals(
                TurbidityThresholdRules.Tier.NONE,
                TurbidityThresholdRules.classify(List.of(p("a", 40), p("b", 120)), 50, 100)
        );
    }

    @Test
    void onePointNoAlert() {
        assertEquals(
                TurbidityThresholdRules.Tier.NONE,
                TurbidityThresholdRules.classify(List.of(p("a", 99)), 50, 100)
        );
    }
}
