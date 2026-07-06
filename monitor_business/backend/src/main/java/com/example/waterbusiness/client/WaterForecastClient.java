package com.example.waterbusiness.client;

import com.example.waterbusiness.dto.ForecastRequest;
import com.example.waterbusiness.dto.ForecastResponse;
import com.example.waterbusiness.dto.ForecastSeriesRequest;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "waterForecastClient", url = "${water.ai.base-url:http://localhost:8000}")
public interface WaterForecastClient {

    @PostMapping(value = "/forecast", consumes = MediaType.APPLICATION_JSON_VALUE)
    ForecastResponse forecast(@RequestBody ForecastRequest request);

    @PostMapping(value = "/forecast/series", consumes = MediaType.APPLICATION_JSON_VALUE)
    ForecastResponse forecastSeries(@RequestBody ForecastSeriesRequest request);
}
