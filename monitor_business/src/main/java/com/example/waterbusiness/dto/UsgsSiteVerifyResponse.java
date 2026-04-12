package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class UsgsSiteVerifyResponse {

    private boolean exists;

    @JsonProperty("site_no")
    private String siteNo;

    /** Message when missing or error; may be null when site exists */
    private String message;
}
