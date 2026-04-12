package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.MapStationPointResponse;
import com.example.waterbusiness.dto.PageResponse;
import com.example.waterbusiness.dto.WaterQualityBatchRequest;
import com.example.waterbusiness.dto.WaterQualityBatchResponse;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import com.example.waterbusiness.entity.WaterQualityRecord;
import com.example.waterbusiness.service.WaterQualityService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "Checks", description = "Water quality checks and record queries")
public class MonitorController {

    private final WaterQualityService waterQualityService;

    @PostMapping("/check")
    @Operation(summary = "Single check", description = "Calls AI, persists record, may raise alert")
    public ApiResponse<WaterQualityResponse> check(@Valid @RequestBody WaterQualityRequest request) {
        return ApiResponse.ok(waterQualityService.checkAndSave(request));
    }

    @PostMapping("/check/batch")
    @Operation(summary = "Batch check", description = "Batch AI calls; one failure does not affect others")
    public ApiResponse<WaterQualityBatchResponse> checkBatch(@Valid @RequestBody WaterQualityBatchRequest body) {
        return ApiResponse.ok(waterQualityService.checkBatch(body.getItems()));
    }

    @GetMapping("/records")
    @Operation(summary = "Paged check records")
    public ApiResponse<PageResponse<WaterQualityRecord>> records(
            @PageableDefault(size = 20, sort = "createTime", direction = Sort.Direction.DESC)
            Pageable pageable
    ) {
        return ApiResponse.ok(PageResponse.from(waterQualityService.listRecords(pageable)));
    }

    @GetMapping("/map/stations")
    @Operation(summary = "Map station snapshot", description = "Coordinates, latest check snapshot, open alert count")
    public ApiResponse<List<MapStationPointResponse>> mapStations() {
        return ApiResponse.ok(waterQualityService.listMapStations());
    }
}
