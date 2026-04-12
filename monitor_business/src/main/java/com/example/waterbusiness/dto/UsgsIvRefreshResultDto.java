package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

/**
 * IV refresh payload for the UI (no large {@code latest_check_payloads} blob).
 */
@Data
@Schema(description = "USGS IV refresh result with optional batch-check summary")
public class UsgsIvRefreshResultDto {

    private String region;

    private Integer sites;

    private List<String> parameters;

    private String start;

    private String end;

    private Integer rows;

    private String out;

    @Schema(description = "Write mode: overwrite means full file replace")
    private String mode;

    @Schema(description = "When post-refresh checks enabled: batch /api/check success count")
    private Integer checkSyncSuccessCount;

    @Schema(description = "When post-refresh checks enabled: batch /api/check failure count")
    private Integer checkSyncFailCount;

    @Schema(description = "New IV rows vs old file (same as Python incremental_rows_new)")
    private Integer incrementalRowsNew;
}
