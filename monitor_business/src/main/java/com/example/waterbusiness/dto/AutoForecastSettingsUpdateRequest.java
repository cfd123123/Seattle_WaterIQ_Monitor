package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "Update auto-forecast toggle")
public class AutoForecastSettingsUpdateRequest {

    @NotNull
    private Boolean enabled;
}
