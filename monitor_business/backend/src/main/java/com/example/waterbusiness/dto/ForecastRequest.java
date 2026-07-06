package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/**
 * Short-horizon forecast request: snake_case JSON matches Python /forecast; camelCase aliases supported.
 */
@Data
@Schema(description = "USGS IV short-horizon forecast request")
public class ForecastRequest {

    @NotBlank
    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    @Schema(description = "USGS 8-digit site number", example = "12117000")
    private String siteNo;

    @NotBlank
    @Pattern(regexp = "\\d{5}", message = "须为 5 位数字 USGS parameterCd")
    @JsonProperty("parameter_cd")
    @JsonAlias("parameterCd")
    @Schema(description = "NWIS parameter_cd; only 00060 (flow) and 63680 (turbidity) allowed", example = "00060")
    private String parameterCd;

    @Min(1)
    @Max(168)
    @JsonProperty("horizon_hours")
    @JsonAlias("horizonHours")
    @Schema(description = "Forecast horizon in hours", example = "24")
    private Integer horizonHours;

    @JsonProperty("iv_csv_path")
    @JsonAlias("ivCsvPath")
    @Schema(description = "Optional IV CSV path on Python side; default ai_service/data/usgs_puget_iv.csv")
    private String ivCsvPath;
}
