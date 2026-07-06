package com.example.waterbusiness.dto;

import lombok.Data;

@Data
public class ForecastSeriesPoint {
    private String timestamp;
    private Double value;
}
