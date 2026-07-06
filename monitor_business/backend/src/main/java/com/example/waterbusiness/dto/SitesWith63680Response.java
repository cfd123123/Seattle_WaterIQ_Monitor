package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
public class SitesWith63680Response {

    @JsonProperty("site_nos")
    private List<String> siteNos;
}
