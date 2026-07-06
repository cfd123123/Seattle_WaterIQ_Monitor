package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.DemoSeedResponse;
import com.example.waterbusiness.service.DemoSeedService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/demo")
@RequiredArgsConstructor
@Tag(name = "Demo data", description = "Dev only: seed fake stations and alerts (requires water.demo-seed.enabled=true)")
@ConditionalOnProperty(name = "water.demo-seed.enabled", havingValue = "true")
public class DemoSeedController {

    private final DemoSeedService demoSeedService;

    @PostMapping("/seed-fake-alerts")
    @Operation(
            summary = "Seed demo stations and fake alerts on half the days in the 7-day window",
            description = "Creates/updates FAKE_SEA_001..003 and writes alerts on 4 days within the same 7-day window as stats for TopN testing. Re-calling deletes prior demo alerts with the same remark then rewrites."
    )
    public ApiResponse<DemoSeedResponse> seedFakeAlerts() {
        return ApiResponse.ok(demoSeedService.seedFakeStationsAndAlerts());
    }
}
