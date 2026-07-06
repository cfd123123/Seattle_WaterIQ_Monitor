package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.UsgsAnomalyFromIvRequest;
import com.example.waterbusiness.dto.UsgsAnomalyRequest;
import com.example.waterbusiness.dto.UsgsAnomalyResponse;
import com.example.waterbusiness.service.UsgsAnomalyService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/usgs")
@RequiredArgsConstructor
@Tag(name = "USGS anomaly", description = "Five-parameter USGS anomaly detection and alerts")
public class UsgsAnomalyController {

    private final UsgsAnomalyService usgsAnomalyService;

    @PostMapping("/anomaly/check")
    @Operation(summary = "USGS parameter anomaly check", description = "Calls AI IsolationForest; may write alert on anomaly.")
    public ApiResponse<UsgsAnomalyResponse> check(@Valid @RequestBody UsgsAnomalyRequest request) {
        return ApiResponse.ok(usgsAnomalyService.detectAndAlert(request));
    }

    @PostMapping("/anomaly/check-from-iv")
    @Operation(
            summary = "Anomaly check from latest five-param IV row",
            description = "Reads latest row with all five core params from local IV wide table, then IsolationForest; may write alert if anomaly and station registered."
    )
    public ApiResponse<UsgsAnomalyResponse> checkFromIv(@Valid @RequestBody UsgsAnomalyFromIvRequest request) {
        return ApiResponse.ok(usgsAnomalyService.detectAndAlertFromIv(request));
    }
}
