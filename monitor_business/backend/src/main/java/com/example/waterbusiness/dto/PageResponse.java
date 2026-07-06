package com.example.waterbusiness.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.domain.Page;

import java.util.List;

/**
 * Stable pagination DTO instead of serializing Spring {@link Page} directly.
 * <ul>
 *     <li>{@code page}: zero-based page index (Spring Data)</li>
 *     <li>{@code size}: page size</li>
 * </ul>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PageResponse<T> {

    private List<T> content;
    private long totalElements;
    private int totalPages;
    /** Zero-based page index */
    private int page;
    private int size;
    private boolean first;
    private boolean last;
    private int numberOfElements;
    private boolean empty;

    public static <T> PageResponse<T> from(Page<T> p) {
        return PageResponse.<T>builder()
                .content(p.getContent())
                .totalElements(p.getTotalElements())
                .totalPages(p.getTotalPages())
                .page(p.getNumber())
                .size(p.getSize())
                .first(p.isFirst())
                .last(p.isLast())
                .numberOfElements(p.getNumberOfElements())
                .empty(p.isEmpty())
                .build();
    }
}
