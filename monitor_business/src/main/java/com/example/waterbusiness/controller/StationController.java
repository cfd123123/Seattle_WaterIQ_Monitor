package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.StationResponse;
import com.example.waterbusiness.dto.StationUpsertRequest;
import com.example.waterbusiness.service.MonitorStationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/stations")
@RequiredArgsConstructor
@Tag(name = "Stations", description = "Station master data CRUD")
public class StationController {

    private final MonitorStationService monitorStationService;

    @PostMapping
    @Operation(summary = "Create station", description = "409 Conflict if stationCode exists; use PUT to update.")
    public ApiResponse<StationResponse> create(@Valid @RequestBody StationUpsertRequest request) {
        return ApiResponse.ok(monitorStationService.create(request));
    }

    @PutMapping("/{stationCode}")
    @Operation(summary = "Update station", description = "Identified by path stationCode; body stationCode must match path if set.")
    public ApiResponse<StationResponse> update(
            @PathVariable("stationCode") String stationCode,
            @Valid @RequestBody StationUpsertRequest request
    ) {
        return ApiResponse.ok(monitorStationService.update(stationCode, request));
    }

    @DeleteMapping("/{stationCode}")
    @Operation(summary = "Delete station", description = "Deletes master row by stationCode; history not cascaded.")
    public ApiResponse<Void> delete(@PathVariable("stationCode") String stationCode) {
        monitorStationService.deleteByStationCode(stationCode);
        return ApiResponse.ok(null);
    }

    @GetMapping
    @Operation(summary = "List stations")
    public ApiResponse<List<StationResponse>> list() {
        return ApiResponse.ok(monitorStationService.list());
    }
}
