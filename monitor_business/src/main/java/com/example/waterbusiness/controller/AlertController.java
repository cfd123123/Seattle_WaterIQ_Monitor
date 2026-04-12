package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.AlertAckRequest;
import com.example.waterbusiness.dto.AlertCloseRequest;
import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.PageResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.service.AlertService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;

@RestController
@RequestMapping("/api/alerts")
@RequiredArgsConstructor
@Tag(name = "Alerts", description = "Alert queries and workflow")
public class AlertController {

    private final AlertService alertService;

    @GetMapping
    @Operation(summary = "Paged alert list")
    public ApiResponse<PageResponse<AlertEvent>> list(
            @RequestParam(required = false) String status,
            @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
            LocalDateTime createdFrom,
            @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
            LocalDateTime createdTo,
            @RequestParam(required = false) String severity,
            @RequestParam(required = false) String pollutionLevel,
            @PageableDefault(size = 20, sort = "createdAt", direction = Sort.Direction.DESC)
            Pageable pageable
    ) {
        return ApiResponse.ok(PageResponse.from(
                alertService.list(pageable, status, createdFrom, createdTo, severity, pollutionLevel)
        ));
    }

    @PostMapping("/{id}/ack")
    @Operation(summary = "Acknowledge alert")
    public ApiResponse<Void> acknowledge(
            @PathVariable Long id,
            @RequestBody(required = false) AlertAckRequest body
    ) {
        alertService.acknowledge(id, body);
        return ApiResponse.ok(null);
    }

    @PostMapping("/{id}/close")
    @Operation(summary = "Close alert")
    public ApiResponse<Void> close(
            @PathVariable Long id,
            @RequestBody(required = false) AlertCloseRequest body
    ) {
        alertService.close(id, body);
        return ApiResponse.ok(null);
    }
}
