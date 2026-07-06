package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

/**
 * IV refresh payload for the UI (metadata only).
 */
@Data
@Schema(description = "USGS IV refresh result")
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

    @Schema(description = "Reserved; may be absent when Python does not compute row diff")
    private Integer incrementalRowsNew;
}
