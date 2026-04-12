package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.service.SiteParamAnomalyService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/usgs/anomaly")
@RequiredArgsConstructor
@Tag(name = "USGS single-param anomaly", description = "On-demand IsolationForest for flow/turbidity")
public class SiteParamAnomalyController {

    private final SiteParamAnomalyService siteParamAnomalyService;

    @PostMapping("/site-param/check")
    @Operation(summary = "Single-station flow or turbidity anomaly check", description = "Python fits on IV hourly series per request; no alert when data insufficient.")
    public ApiResponse<SiteParamAnomalyIvResponse> check(@Valid @RequestBody SiteParamAnomalyIvRequest request) {
        return ApiResponse.ok(siteParamAnomalyService.detectAndAlert(request));
    }
}
