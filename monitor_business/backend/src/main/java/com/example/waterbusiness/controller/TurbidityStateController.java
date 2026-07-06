package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.TurbidityStateCheckResponse;
import com.example.waterbusiness.dto.TurbidityStateScanResult;
import com.example.waterbusiness.dto.TurbidityStateSnapshotResponse;
import com.example.waterbusiness.service.TurbidityStateAlertService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/usgs/turbidity-state")
@RequiredArgsConstructor
@Tag(name = "USGS turbidity state", description = "Four-state monitoring via Python /turbidity/state/*")
public class TurbidityStateController {

    private final TurbidityStateAlertService turbidityStateAlertService;

    @GetMapping("/snapshot")
    @Operation(summary = "Latest turbidity state snapshot (no alert)")
    public ApiResponse<TurbidityStateSnapshotResponse> snapshot(
            @RequestParam(defaultValue = "12117500") String siteNo,
            @RequestParam(required = false) String referenceUtc
    ) {
        return ApiResponse.ok(turbidityStateAlertService.fetchSnapshot(siteNo, referenceUtc));
    }

    @PostMapping("/check")
    @Operation(summary = "Snapshot + create alert_event when state/rule triggers")
    public ApiResponse<TurbidityStateCheckResponse> check(
            @RequestParam(defaultValue = "12117500") String siteNo,
            @RequestParam(required = false) String referenceUtc
    ) {
        return ApiResponse.ok(turbidityStateAlertService.checkAndAlert(siteNo, referenceUtc));
    }

    @PostMapping("/scan")
    @Operation(summary = "Scan all registered monitored sites (same as scheduler)")
    public ApiResponse<TurbidityStateScanResult> scanNow() {
        return ApiResponse.ok(turbidityStateAlertService.scanAndAlert());
    }
}
