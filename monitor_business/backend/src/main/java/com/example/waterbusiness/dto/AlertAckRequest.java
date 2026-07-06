package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "Alert acknowledge request body")
public class AlertAckRequest {

    @Schema(description = "Acknowledged by", example = "operator01")
    private String acknowledgedBy;
    @Schema(description = "Remark", example = "Verified; scheduling field follow-up")
    private String remark;
}
