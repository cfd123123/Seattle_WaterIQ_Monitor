package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * One element of Python {@code latest_check_payloads[]}.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class UsgsIvLatestCheckItem {

    @JsonProperty("site_no")
    private String siteNo;

    private Map<String, Object> payload;

    @JsonProperty("observed_fields")
    private List<String> observedFields;

    /** IV sample time (UTC ISO) for audit */
    private String datetime;
}
