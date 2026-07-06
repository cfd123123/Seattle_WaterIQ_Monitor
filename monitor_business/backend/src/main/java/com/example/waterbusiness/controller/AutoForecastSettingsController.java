package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.AutoForecastRunNowResponse;
import com.example.waterbusiness.dto.AutoForecastSettingsResponse;
import com.example.waterbusiness.dto.AutoForecastSettingsUpdateRequest;
import com.example.waterbusiness.service.AutoForecastBatchService;
import com.example.waterbusiness.service.AutoForecastSettingsService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/forecast")
@RequiredArgsConstructor
@Tag(name = "Forecast", description = "Automatic forecast toggle")
public class AutoForecastSettingsController {

    private final AutoForecastSettingsService autoForecastSettingsService;
    private final AutoForecastBatchService autoForecastBatchService;

    @GetMapping("/auto-settings")
    @Operation(summary = "Get auto-forecast toggle and last run summary")
    public ApiResponse<AutoForecastSettingsResponse> getAutoSettings() {
        return ApiResponse.ok(autoForecastSettingsService.getResponse());
    }

    @PutMapping("/auto-settings")
    @Operation(summary = "Update auto-forecast toggle", description = "When enabled, server runs batch forecasts on cron (requires AI and IV data).")
    public ApiResponse<AutoForecastSettingsResponse> updateAutoSettings(
            @Valid @RequestBody AutoForecastSettingsUpdateRequest body
    ) {
        return ApiResponse.ok(autoForecastSettingsService.setEnabled(Boolean.TRUE.equals(body.getEnabled())));
    }

    @PostMapping("/auto-settings/run-now")
    @Operation(
            summary = "Run one auto-forecast batch now",
            description = "Same batch logic as the scheduler (all registered stations with non-empty externalId × 00060/63680); does not depend on enabled; for dev and verification."
    )
    public ApiResponse<AutoForecastRunNowResponse> runBatchNow() {
        var exec = autoForecastBatchService.executeBatch();
        return ApiResponse.ok(
                AutoForecastRunNowResponse.builder()
                        .settings(autoForecastSettingsService.getResponse())
                        .batchResults(exec.batchResults())
                        .build()
        );
    }
}
