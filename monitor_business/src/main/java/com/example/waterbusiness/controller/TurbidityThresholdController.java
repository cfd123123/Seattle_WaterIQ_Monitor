package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.TurbidityThresholdScanResult;
import com.example.waterbusiness.service.TurbidityThresholdAlertService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/usgs/turbidity-threshold")
@RequiredArgsConstructor
@Tag(name = "USGS turbidity threshold", description = "63680 two-point absolute threshold alerts")
public class TurbidityThresholdController {

    private final TurbidityThresholdAlertService turbidityThresholdAlertService;

    @PostMapping("/scan")
    @Operation(summary = "Scan IV now for turbidity threshold alerts", description = "Same logic as scheduler; does not depend on enabled flag")
    public ApiResponse<TurbidityThresholdScanResult> scanNow() {
        return ApiResponse.ok(turbidityThresholdAlertService.scanAndAlert());
    }
}
