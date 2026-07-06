package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class HistoryMessageDto {

    private String role;

    private String content;
}
