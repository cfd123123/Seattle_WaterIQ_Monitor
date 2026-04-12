package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "Alert close request body")
public class AlertCloseRequest {

    /** Closer; empty uses anonymous */
    @Schema(description = "Closer (empty stored as anonymous)", example = "operator01")
    private String closedBy;

    /** Optional close remark */
    @Schema(description = "Close remark", example = "Verified on site, closing alert")
    private String remark;
}
