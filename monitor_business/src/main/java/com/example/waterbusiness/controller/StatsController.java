package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.StatsDistributionResponse;
import com.example.waterbusiness.dto.StatsOverviewResponse;
import com.example.waterbusiness.dto.StatsStationAlertTopResponse;
import com.example.waterbusiness.dto.StatsTrendResponse;
import com.example.waterbusiness.service.StatsService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

@RestController
@RequestMapping("/api/stats")
@RequiredArgsConstructor
@Tag(name = "Stats", description = "Overview, distribution, trends")
public class StatsController {

    private final StatsService statsService;

    @GetMapping("/overview")
    @Operation(summary = "Stats overview")
    public ApiResponse<StatsOverviewResponse> overview() {
        return ApiResponse.ok(statsService.overview());
    }

    @GetMapping("/distribution")
    @Operation(summary = "Distribution", description = "Omit dates for all-time; pass from/to for a range")
    public ApiResponse<StatsDistributionResponse> distribution(
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to
    ) {
        return ApiResponse.ok(statsService.distribution(from, to));
    }

    @GetMapping("/trend")
    @Operation(
            summary = "Daily USGS alert trend",
            description = "granularity is day only. Buckets alert_event into four USGS series; no longer aggregates water_quality_record."
    )
    public ApiResponse<StatsTrendResponse> trend(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(defaultValue = "day") String granularity,
            @RequestParam(required = false) Long stationId
    ) {
        return ApiResponse.ok(statsService.trend(from, to, granularity, stationId));
    }

    @GetMapping("/station-alert-top")
    @Operation(summary = "Station alert TopN for last N days", description = "Descending by alert count (default 7 days, top 5)")
    public ApiResponse<StatsStationAlertTopResponse> stationAlertTop(
            @RequestParam(defaultValue = "7") int days,
            @RequestParam(name = "topN", defaultValue = "5") int topN
    ) {
        return ApiResponse.ok(statsService.stationAlertTop(days, topN));
    }
}
