package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.MapStationPointResponse;
import com.example.waterbusiness.service.MapStationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "Map", description = "Station map snapshot (USGS-era; alert-derived)")
public class MonitorController {

    private final MapStationService mapStationService;

    @GetMapping("/map/stations")
    @Operation(
            summary = "Map station snapshot",
            description = "Coordinates, latest alert pollution level/time, open alert count"
    )
    public ApiResponse<List<MapStationPointResponse>> mapStations() {
        return ApiResponse.ok(mapStationService.listMapStations());
    }
}
