package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(description = "Single row in batch check response")
public class WaterQualityBatchItemResult {

    /** Index in request list, zero-based */
    @Schema(description = "Index in request list (0-based)", example = "0")
    private int index;
    @Schema(description = "Whether this row succeeded", example = "true")
    private boolean success;
    @Schema(description = "Prediction payload when success")
    private WaterQualityResponse data;
    @Schema(description = "Error message when failed", example = "AI unavailable")
    private String errorMessage;
}
