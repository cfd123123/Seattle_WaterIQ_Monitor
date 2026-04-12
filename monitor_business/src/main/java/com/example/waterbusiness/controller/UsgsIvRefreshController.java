package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.UsgsIvRefreshRequest;
import com.example.waterbusiness.dto.UsgsIvRefreshResultDto;
import com.example.waterbusiness.service.UsgsIvRefreshService;
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
@Tag(name = "USGS IV", description = "Manual IV CSV refresh (proxies Python POST /refresh/usgs-iv)")
public class UsgsIvRefreshController {

    private final UsgsIvRefreshService usgsIvRefreshService;

    @PostMapping("/usgs/iv/refresh")
    @Operation(
            summary = "Manually refresh IV CSV",
            description = "Pulls from NWIS and **overwrites** ai_service/data/usgs_puget_iv.csv for the last N days."
                    + " Optionally runs the same persist/alert flow as /api/check for **new (site_no,datetime) rows** vs the old file (≤100 rows per batch)."
    )
    public ApiResponse<UsgsIvRefreshResultDto> refresh(
            @Valid @RequestBody(required = false) UsgsIvRefreshRequest request
    ) {
        return ApiResponse.ok(usgsIvRefreshService.refreshWithRetry(request));
    }
}
