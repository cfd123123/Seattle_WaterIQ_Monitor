package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
@Schema(description = "Anomaly check from latest IV row with all five core params")
public class UsgsAnomalyFromIvRequest {

    @NotBlank
    @JsonProperty("site_no")
    @Schema(description = "USGS site number", example = "12117000")
    private String siteNo;

    @JsonProperty("iv_csv_path")
    @Schema(description = "Optional; same as /api/forecast; default AI IV path")
    private String ivCsvPath;
}
