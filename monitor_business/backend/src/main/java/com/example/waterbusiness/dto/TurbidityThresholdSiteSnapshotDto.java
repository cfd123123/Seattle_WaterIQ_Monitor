package com.example.waterbusiness.dto;

import lombok.Data;

import java.util.List;

@Data
public class TurbidityThresholdSiteSnapshotDto {

    private boolean available;

    private List<TurbidityThresholdPointDto> points;

    private String reason;
}
