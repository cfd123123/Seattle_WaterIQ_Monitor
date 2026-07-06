package com.example.waterbusiness.dto;

import com.example.waterbusiness.common.TraceIdFilter;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.slf4j.MDC;

import java.time.Instant;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiResponse<T> {

    private String code;
    private String message;
    private T data;
    private String traceId;
    private Instant timestamp;

    public static <T> ApiResponse<T> ok(T data) {
        return ApiResponse.<T>builder()
                .code("0")
                .message("OK")
                .data(data)
                .traceId(MDC.get(TraceIdFilter.MDC_KEY))
                .timestamp(Instant.now())
                .build();
    }

    public static <T> ApiResponse<T> fail(String code, String message) {
        return ApiResponse.<T>builder()
                .code(code)
                .message(message)
                .traceId(MDC.get(TraceIdFilter.MDC_KEY))
                .timestamp(Instant.now())
                .build();
    }
}
