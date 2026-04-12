package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.ForecastRequest;
import com.example.waterbusiness.dto.ForecastResponse;
import com.example.waterbusiness.dto.ForecastSeriesRequest;
import com.example.waterbusiness.service.ForecastService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "Forecast", description = "USGS IV short-horizon forecast (proxies Python /forecast)")
public class ForecastController {

    private final ForecastService forecastService;

    @PostMapping("/forecast")
    @Operation(summary = "Short-horizon forecast", description = "Proxies AI POST /forecast using merged IV CSV")
    public ApiResponse<ForecastResponse> forecast(@Valid @RequestBody ForecastRequest request) {
        return ApiResponse.ok(forecastService.forecastWithRetry(request));
    }

    @PostMapping("/forecast/series")
    @Operation(summary = "Forecast series", description = "Proxies AI POST /forecast/series (history solid + forecast dashed)")
    public ApiResponse<ForecastResponse> forecastSeries(@Valid @RequestBody ForecastSeriesRequest request) {
        return ApiResponse.ok(forecastService.forecastSeriesWithRetry(request));
    }
}
