package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.TurbidityRiskForecast12hResponse;
import com.example.waterbusiness.service.TurbidityRiskForecastService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/usgs/turbidity-risk")
@RequiredArgsConstructor
@Tag(name = "USGS turbidity risk", description = "12h alert-risk forecast (Phase B; not NTU curve)")
public class TurbidityRiskForecastController {

    private final TurbidityRiskForecastService turbidityRiskForecastService;

    @PostMapping("/forecast-12h")
    @Operation(summary = "12h turbidity alert-risk forecast for site 12117500")
    public ApiResponse<TurbidityRiskForecast12hResponse> forecast12h(
            @RequestParam(defaultValue = "12117500") String siteNo,
            @RequestParam(required = false) String referenceUtc
    ) {
        return ApiResponse.ok(turbidityRiskForecastService.fetchForecast(siteNo, referenceUtc));
    }

    @PostMapping("/risk-explain")
    @Operation(summary = "12h turbidity risk forecast with LLM explanation (MVP-1)")
    public ApiResponse<TurbidityRiskForecast12hResponse> riskExplain(
            @RequestParam(defaultValue = "12117500") String siteNo,
            @RequestParam(required = false) String referenceUtc
    ) {
        return ApiResponse.ok(turbidityRiskForecastService.fetchForecastWithExplain(siteNo, referenceUtc));
    }
}
