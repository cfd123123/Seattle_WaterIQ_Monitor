package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

/**
 * Metadata returned by Python {@code /refresh/usgs-iv}.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "USGS IV refresh result summary")
public class UsgsIvRefreshResponse {

    private String region;

    private Integer sites;

    private List<String> parameters;

    private String start;

    private String end;

    private Integer rows;

    private String out;

    @JsonProperty("mode")
    @Schema(description = "Write mode: overwrite means full file replace")
    private String mode;

    @JsonProperty("incremental_rows_new")
    @Schema(description = "New (site_no,datetime) rows vs old CSV, for batch checks")
    private Integer incrementalRowsNew;

    /**
     * Rows in diff vs IV file before overwrite; legacy key latest_check_payloads accepted.
     */
    @JsonProperty("incremental_check_payloads")
    @JsonAlias("latest_check_payloads")
    private List<UsgsIvLatestCheckItem> incrementalCheckPayloads;
}
